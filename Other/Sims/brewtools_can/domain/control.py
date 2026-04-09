# brewtools_can/domain/control.py
from __future__ import annotations

from dataclasses import dataclass

from ..bodies import RawBody
from ..frame import CanFrame
from .base import node_id_from_frame


@dataclass(frozen=True)
class ControlMessage:
    node_id: int
    subindex: int
    raw: bytes


def decode_control_raw(frame: CanFrame) -> ControlMessage | None:
    if not isinstance(frame.body, RawBody):
        return None
    return ControlMessage(
        node_id_from_frame(frame), frame.body.subindex, frame.body.raw
    )
