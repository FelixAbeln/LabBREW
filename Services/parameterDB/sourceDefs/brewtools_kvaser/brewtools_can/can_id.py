from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrewtoolsCanId:
    """
    29-bit extended CAN ID layout:
      priority:         bits 28..27 (2 bits)
      sender_node_type: bits 26..19 (8 bits)
      receiver_node_type: bits 18..11 (8 bits)
      secondary_node_id: bits 10..8 (3 bits)
      msg_type:         bits 7..0 (8 bits)
    """
    priority: int
    sender_node_type: int
    receiver_node_type: int
    secondary_node_id: int
    msg_type: int

    def to_arbitration_id(self) -> int:
        return (
            ((self.priority & 0x03) << 27) |
            ((self.sender_node_type & 0xFF) << 19) |
            ((self.receiver_node_type & 0xFF) << 11) |
            ((self.secondary_node_id & 0x07) << 8) |
            (self.msg_type & 0xFF)
        )

    @staticmethod
    def from_arbitration_id(arbitration_id: int) -> BrewtoolsCanId:
        priority = (arbitration_id >> 27) & 0x03
        sender = (arbitration_id >> 19) & 0xFF
        receiver = (arbitration_id >> 11) & 0xFF
        secondary = (arbitration_id >> 8) & 0x07
        msg_type = arbitration_id & 0xFF
        return BrewtoolsCanId(priority, sender, receiver, secondary, msg_type)
