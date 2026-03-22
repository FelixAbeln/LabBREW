from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from ..bodies import CalibrationAckBody, RawBody
from ..frame import CanFrame
from ..can_id import BrewtoolsCanId
from ..enums import MsgType, Priority, NodeType
from .base import DomainMessage, node_id_from_frame

@dataclass(frozen=True)
class CalibrationAck:
    node_id: int
    ack_type: int
    subindex: int
    extra: bytes = b""

def decode_calibration_ack(frame: CanFrame) -> Optional[CalibrationAck]:
    if not isinstance(frame.body, CalibrationAckBody):
        return None
    return CalibrationAck(node_id_from_frame(frame), frame.body.ack_type, frame.body.subindex, frame.body.extra)

# Calibration command payload is not fully specified in the doc page beyond subIndex+bytes,
# so we keep it lossless for now.
@dataclass(frozen=True)
class CalibrationCmd(DomainMessage):
    target_node_id: int
    raw: bytes = b""
    subindex: int = 0
    sender_node_type: int = NodeType.NODE_TYPE_PLC
    receiver_node_type: int = NodeType.NODE_TYPE_DENSITY_SENSOR
    priority: int = Priority.MEDIUM

    def to_frame(self) -> CanFrame:
        can_id = BrewtoolsCanId(
            priority=int(self.priority),
            sender_node_type=int(self.sender_node_type),
            receiver_node_type=int(self.receiver_node_type),
            secondary_node_id=int(self.target_node_id),
            msg_type=int(MsgType.MSG_TYPE_CALIBRATION_CMD),
        )
        return CanFrame(can_id, RawBody(subindex=self.subindex, raw=self.raw))

@dataclass(frozen=True)
class CalibrationCmdReceived:
    node_id: int
    subindex: int
    raw: bytes

def decode_calibration_cmd(frame: CanFrame) -> Optional[CalibrationCmdReceived]:
    # likely RawBody unless you later define a real body
    if not hasattr(frame.body, "subindex"):
        return None
    sub = int(getattr(frame.body, "subindex"))
    raw = getattr(frame.body, "raw", b"")  # works if RawBody
    if isinstance(raw, bytes):
        return CalibrationCmdReceived(node_id_from_frame(frame), sub, raw)
    return None
