from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple
import struct

from .exceptions import DecodeError


class Body(Protocol):
    subindex: int

    def encode(self) -> bytes: ...

    @classmethod
    def decode(cls, data: bytes) -> "Body": ...


def split_subindex(data: bytes) -> Tuple[int, bytes]:
    if not data:
        raise DecodeError("Empty payload; expected at least subIndex byte.")
    return data[0], data[1:]


@dataclass(frozen=True)
class FloatBody:
    """subIndex + IEEE754 float32 little-endian"""
    subindex: int
    value: float

    def encode(self) -> bytes:
        return bytes([self.subindex & 0xFF]) + struct.pack("<f", self.value)

    @classmethod
    def decode(cls, data: bytes) -> "FloatBody":
        sub, raw = split_subindex(data)
        if len(raw) < 4:
            raise DecodeError(f"FloatBody needs 4 bytes after subIndex, got {len(raw)}.")
        (value,) = struct.unpack("<f", raw[:4])
        return cls(sub, value)


@dataclass(frozen=True)
class NodeIdBody:
    """subIndex + u32 big-endian (docs example)"""
    subindex: int
    new_node_id: int

    def encode(self) -> bytes:
        if not (0 <= int(self.new_node_id) <= 0xFFFFFFFF):
            raise ValueError("new_node_id out of range (0..2^32-1)")
        return bytes([self.subindex & 0xFF]) + int(self.new_node_id).to_bytes(4, "big", signed=False)

    @classmethod
    def decode(cls, data: bytes) -> "NodeIdBody":
        sub, raw = split_subindex(data)
        if len(raw) < 4:
            raise DecodeError(f"NodeIdBody needs 4 bytes after subIndex, got {len(raw)}.")
        new_id = int.from_bytes(raw[:4], "big", signed=False)
        return cls(sub, new_id)


@dataclass(frozen=True)
class CalibrationAckBody:
    """subIndex + ack_type byte (+ optional extra bytes)"""
    subindex: int
    ack_type: int
    extra: bytes = b""

    def encode(self) -> bytes:
        return bytes([self.subindex & 0xFF, self.ack_type & 0xFF]) + (self.extra or b"")

    @classmethod
    def decode(cls, data: bytes) -> "CalibrationAckBody":
        sub, raw = split_subindex(data)
        if len(raw) < 1:
            raise DecodeError("CalibrationAckBody needs 1 byte after subIndex (ack_type).")
        return cls(sub, raw[0], raw[1:])


@dataclass(frozen=True)
class RawBody:
    """Fallback: preserves raw bytes after subIndex."""
    subindex: int
    raw: bytes

    def encode(self) -> bytes:
        return bytes([self.subindex & 0xFF]) + (self.raw or b"")

    @classmethod
    def decode(cls, data: bytes) -> "RawBody":
        sub, raw = split_subindex(data)
        return cls(sub, raw)
