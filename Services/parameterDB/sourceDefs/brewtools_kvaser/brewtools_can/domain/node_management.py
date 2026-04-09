from __future__ import annotations

from dataclasses import dataclass

from ..bodies import NodeIdBody
from ..can_id import BrewtoolsCanId
from ..enums import MsgType, NodeType, Priority
from ..frame import CanFrame
from .base import DomainMessage, node_id_from_frame


@dataclass(frozen=True)
class NodeIdUpdate(DomainMessage):
    old_node_id: int
    new_node_id: int
    subindex: int = 0
    sender_node_type: int = NodeType.NODE_TYPE_PLC
    receiver_node_type: int = NodeType.NODE_TYPE_DENSITY_SENSOR
    priority: int = Priority.MEDIUM

    def to_frame(self) -> CanFrame:
        can_id = BrewtoolsCanId(
            priority=int(self.priority),
            sender_node_type=int(self.sender_node_type),
            receiver_node_type=int(self.receiver_node_type),
            secondary_node_id=int(self.old_node_id),
            msg_type=int(MsgType.MSG_TYPE_NODE_ID),
        )
        return CanFrame(
            can_id, NodeIdBody(subindex=self.subindex, new_node_id=self.new_node_id)
        )


def decode_node_id_update(frame: CanFrame) -> NodeIdUpdate | None:
    if not isinstance(frame.body, NodeIdBody):
        return None
    return NodeIdUpdate(
        old_node_id=node_id_from_frame(frame),
        new_node_id=frame.body.new_node_id,
        subindex=frame.body.subindex,
    )
