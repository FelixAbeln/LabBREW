from __future__ import annotations
from typing import Optional, Protocol, runtime_checkable
from ..frame import CanFrame

@runtime_checkable
class DomainMessage(Protocol):
    """Domain object that can be encoded to a CanFrame (Level 4 send)."""
    def to_frame(self) -> CanFrame: ...

def node_id_from_frame(frame: CanFrame) -> int:
    return int(frame.can_id.secondary_node_id)
