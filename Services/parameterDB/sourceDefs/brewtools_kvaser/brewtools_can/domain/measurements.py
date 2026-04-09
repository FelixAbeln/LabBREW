from __future__ import annotations

from dataclasses import dataclass

from ..bodies import FloatBody
from ..frame import CanFrame
from .base import node_id_from_frame


@dataclass(frozen=True)
class TemperatureMeasurement:
    node_id: int
    value_c: float
    subindex: int


def decode_temperature(frame: CanFrame) -> TemperatureMeasurement | None:
    if not isinstance(frame.body, FloatBody):
        return None
    return TemperatureMeasurement(
        node_id_from_frame(frame), frame.body.value, frame.body.subindex
    )


# Repeat pattern for Pressure/Density/Level/RPM/Min/Max
@dataclass(frozen=True)
class PressureMeasurement:
    node_id: int
    value_bar: float
    subindex: int


def decode_pressure(frame: CanFrame) -> PressureMeasurement | None:
    if not isinstance(frame.body, FloatBody):
        return None
    return PressureMeasurement(
        node_id_from_frame(frame), frame.body.value, frame.body.subindex
    )


@dataclass(frozen=True)
class DensityMeasurement:
    node_id: int
    value: float
    subindex: int


def decode_density(frame: CanFrame) -> DensityMeasurement | None:
    if not isinstance(frame.body, FloatBody):
        return None
    return DensityMeasurement(
        node_id_from_frame(frame), frame.body.value, frame.body.subindex
    )


@dataclass(frozen=True)
class LevelMeasurement:
    node_id: int
    value: float
    subindex: int


def decode_level(frame: CanFrame) -> LevelMeasurement | None:
    if not isinstance(frame.body, FloatBody):
        return None
    return LevelMeasurement(
        node_id_from_frame(frame), frame.body.value, frame.body.subindex
    )


@dataclass(frozen=True)
class RpmMeasurement:
    node_id: int
    value_rpm: float
    subindex: int


def decode_rpm(frame: CanFrame) -> RpmMeasurement | None:
    if not isinstance(frame.body, FloatBody):
        return None
    return RpmMeasurement(
        node_id_from_frame(frame), frame.body.value, frame.body.subindex
    )


@dataclass(frozen=True)
class MinValue:
    node_id: int
    value: float
    subindex: int


def decode_min(frame: CanFrame) -> MinValue | None:
    if not isinstance(frame.body, FloatBody):
        return None
    return MinValue(node_id_from_frame(frame), frame.body.value, frame.body.subindex)


@dataclass(frozen=True)
class MaxValue:
    node_id: int
    value: float
    subindex: int


def decode_max(frame: CanFrame) -> MaxValue | None:
    if not isinstance(frame.body, FloatBody):
        return None
    return MaxValue(node_id_from_frame(frame), frame.body.value, frame.body.subindex)
