from __future__ import annotations

from typing import ClassVar

from .bodies import Body, CalibrationAckBody, FloatBody, NodeIdBody, RawBody
from .enums import MsgType


class BodyFactory:
    """Maps msg_type -> Body class. Unknowns become RawBody."""

    _by_msg_type: ClassVar[dict[int, type[Body]]] = {}

    @classmethod
    def clear(cls) -> None:
        cls._by_msg_type.clear()

    @classmethod
    def register(cls, msg_type: int, body_cls: type[Body]) -> None:
        cls._by_msg_type[int(msg_type)] = body_cls

    @classmethod
    def decode_body(cls, msg_type: int, data: bytes) -> Body:
        body_cls = cls._by_msg_type.get(int(msg_type))
        if body_cls is None:
            return RawBody.decode(data)
        return body_cls.decode(data)


def register_default_bodies() -> None:
    """Register decoders for msg types in the docs
    where payloads are known.
    """
    float_types = [
        MsgType.MSG_TYPE_TEMPERATURE,
        MsgType.MSG_TYPE_PRESSURE,
        MsgType.MSG_TYPE_DENSITY,
        MsgType.MSG_TYPE_LEVEL,
        MsgType.MSG_TYPE_RPM,
        MsgType.MSG_TYPE_MIN,
        MsgType.MSG_TYPE_MAX,
    ]
    for t in float_types:
        BodyFactory.register(t, FloatBody)

    BodyFactory.register(MsgType.MSG_TYPE_NODE_ID, NodeIdBody)
    BodyFactory.register(MsgType.MSG_TYPE_CALIBRATION_ACK, CalibrationAckBody)
