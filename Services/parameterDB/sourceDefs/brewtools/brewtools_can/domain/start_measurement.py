from __future__ import annotations

from dataclasses import dataclass

from ..bodies import RawBody
from ..can_id import BrewtoolsCanId
from ..enums import MsgType, NodeType, Priority
from ..frame import CanFrame
from .base import DomainMessage, node_id_from_frame


# Command to tell a device to start streaming measurements.
# Doc pattern for commands: data[0]=subIndex, remaining bytes optional.
@dataclass(frozen=True)
class StartMeasurementCmd(DomainMessage):
    target_node_id: int                 # secondary_node_id (0..7)
    subindex: int = 0
    raw: bytes = b""                    # optional parameters
    sender_node_type: int = NodeType.NODE_TYPE_PLC
    receiver_node_type: int = NodeType.NODE_TYPE_DENSITY_SENSOR
    priority: int = Priority.MEDIUM

    def to_frame(self) -> CanFrame:
        can_id = BrewtoolsCanId(
            priority=int(self.priority),
            sender_node_type=int(self.sender_node_type),
            receiver_node_type=int(self.receiver_node_type),
            secondary_node_id=int(self.target_node_id),
            msg_type=int(MsgType.MSG_TYPE_START_MEASUREMENT_CMD),
        )
        return CanFrame(can_id, RawBody(subindex=self.subindex, raw=self.raw))


@dataclass(frozen=True)
class StartMeasurementCmdReceived:
    node_id: int
    subindex: int
    raw: bytes

def decode_start_measurement_cmd(frame: CanFrame) -> StartMeasurementCmdReceived | None:
    # likely RawBody unless you later define a real body
    if not hasattr(frame.body, "subindex"):
        return None
    sub = int(frame.body.subindex)
    raw = getattr(frame.body, "raw", b"")
    if isinstance(raw, bytes):
        return StartMeasurementCmdReceived(node_id_from_frame(frame), sub, raw)
    return None
