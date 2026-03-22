from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .can_id import BrewtoolsCanId
from .bodies import Body
from .factory import BodyFactory


@dataclass(frozen=True)
class CanFrame:
    can_id: BrewtoolsCanId
    body: Body

    def to_can(self) -> Tuple[int, bytes]:
        """(extended_arbitration_id, data_bytes)."""
        return self.can_id.to_arbitration_id(), self.body.encode()

    @classmethod
    def from_can(cls, arbitration_id: int, data: bytes) -> "CanFrame":
        can_id = BrewtoolsCanId.from_arbitration_id(arbitration_id)
        body = BodyFactory.decode_body(can_id.msg_type, data)
        return cls(can_id=can_id, body=body)
