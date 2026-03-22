from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from ..bodies import FloatBody
from ..frame import CanFrame
from .base import node_id_from_frame

@dataclass(frozen=True)
class TemperatureMeasurement:
    node_id: int
    value_c: float
    subindex: int

def decode_temperature(frame: CanFrame) -> Optional[TemperatureMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return TemperatureMeasurement(node_id_from_frame(frame), frame.body.value, frame.body.subindex)

# Repeat pattern for Pressure/Density/Level/RPM/Min/Max
@dataclass(frozen=True)
class PressureMeasurement:
    node_id: int
    value_bar: float
    subindex: int

def decode_pressure(frame: CanFrame) -> Optional[PressureMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return PressureMeasurement(node_id_from_frame(frame), frame.body.value, frame.body.subindex)

@dataclass(frozen=True)
class DensityMeasurement:
    node_id: int
    value: float
    subindex: int

def decode_density(frame: CanFrame) -> Optional[DensityMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return DensityMeasurement(node_id_from_frame(frame), frame.body.value, frame.body.subindex)

@dataclass(frozen=True)
class LevelMeasurement:
    node_id: int
    value: float
    subindex: int

def decode_level(frame: CanFrame) -> Optional[LevelMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return LevelMeasurement(node_id_from_frame(frame), frame.body.value, frame.body.subindex)

@dataclass(frozen=True)
class RpmMeasurement:
    node_id: int
    value_rpm: float
    subindex: int

def decode_rpm(frame: CanFrame) -> Optional[RpmMeasurement]:
    if not isinstance(frame.body, FloatBody):
        return None
    return RpmMeasurement(node_id_from_frame(frame), frame.body.value, frame.body.subindex)

@dataclass(frozen=True)
class MinValue:
    node_id: int
    value: float
    subindex: int

def decode_min(frame: CanFrame) -> Optional[MinValue]:
    if not isinstance(frame.body, FloatBody):
        return None
    return MinValue(node_id_from_frame(frame), frame.body.value, frame.body.subindex)

@dataclass(frozen=True)
class MaxValue:
    node_id: int
    value: float
    subindex: int

def decode_max(frame: CanFrame) -> Optional[MaxValue]:
    if not isinstance(frame.body, FloatBody):
        return None
    return MaxValue(node_id_from_frame(frame), frame.body.value, frame.body.subindex)
