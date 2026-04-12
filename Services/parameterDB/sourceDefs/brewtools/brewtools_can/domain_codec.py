from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain_factory import DomainFactory
from .frame import CanFrame


@runtime_checkable
class DomainMessage(Protocol):
    """Domain object that can be sent (build a CanFrame)."""
    def to_frame(self) -> CanFrame: ...


def frame_to_object(frame: CanFrame) -> object | None:
    """CAN frame -> domain object (Level 3 build)."""
    return DomainFactory.build(frame)


def object_to_frame(obj: object) -> CanFrame:
    """Domain object -> CAN frame (Level 4 send)."""
    if not isinstance(obj, DomainMessage):
        raise TypeError(f"{type(obj).__name__} is not sendable (missing to_frame()).")
    return obj.to_frame()


class DomainCodec:
    """Convenience wrapper for both directions."""
    @staticmethod
    def decode(arbitration_id: int, data: bytes) -> object | None:
        frame = CanFrame.from_can(arbitration_id, data)
        return frame_to_object(frame)

    @staticmethod
    def encode(obj: object) -> tuple[int, bytes]:
        frame = object_to_frame(obj)
        return frame.to_can()
