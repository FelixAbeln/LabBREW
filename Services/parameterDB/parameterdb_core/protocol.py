from __future__ import annotations

import struct
import uuid
from typing import Any, BinaryIO

import msgpack

from .errors import ProtocolError


PROTOCOL_VERSION = 1
_LENGTH_STRUCT = struct.Struct("!I")


def encode_message(payload: dict[str, Any]) -> bytes:
    body = msgpack.packb(payload, use_bin_type=True)
    return _LENGTH_STRUCT.pack(len(body)) + body


def decode_message_bytes(data: bytes) -> dict[str, Any]:
    try:
        obj = msgpack.unpackb(data, raw=False)
    except Exception as exc:
        raise ProtocolError(f"Invalid message payload: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("Message must be a map/object")
    return obj


def _read_exact(stream: BinaryIO, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if chunks:
                raise ProtocolError("Incomplete framed message")
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    header = _read_exact(stream, _LENGTH_STRUCT.size)
    if header is None:
        return None
    (length,) = _LENGTH_STRUCT.unpack(header)
    if length <= 0:
        raise ProtocolError(f"Invalid frame length: {length}")
    body = _read_exact(stream, length)
    if body is None:
        raise ProtocolError("Incomplete message body")
    return decode_message_bytes(body)


def make_request(cmd: str, payload: dict[str, Any] | None = None, req_id: str | None = None) -> dict[str, Any]:
    if not isinstance(cmd, str) or not cmd.strip():
        raise ProtocolError("Request cmd must be a non-empty string")
    return {
        "v": PROTOCOL_VERSION,
        "req_id": req_id or uuid.uuid4().hex,
        "cmd": cmd,
        "payload": payload or {},
    }


def make_response(*, req_id: str | None, result: Any = None) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "req_id": req_id,
        "ok": True,
        "result": result,
        "error": None,
    }


def make_error_response(*, req_id: str | None, error_type: str, message: str) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "req_id": req_id,
        "ok": False,
        "result": None,
        "error": {
            "type": error_type,
            "message": message,
        },
    }


def validate_request_envelope(msg: dict[str, Any]) -> tuple[str, str | None, dict[str, Any]]:
    if not isinstance(msg, dict):
        raise ProtocolError("Request must be a dict")

    version = msg.get("v")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version: {version!r}")

    cmd = msg.get("cmd")
    if not isinstance(cmd, str) or not cmd.strip():
        raise ProtocolError("Missing or invalid 'cmd'")

    req_id = msg.get("req_id")
    if req_id is not None and not isinstance(req_id, str):
        raise ProtocolError("Invalid 'req_id'")

    payload = msg.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("Invalid 'payload', expected dict")

    return cmd, req_id, payload


def validate_response_envelope(msg: dict[str, Any]) -> tuple[bool, str | None, Any, dict[str, Any] | None]:
    if not isinstance(msg, dict):
        raise ProtocolError("Response must be a dict")

    version = msg.get("v")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version: {version!r}")

    ok = msg.get("ok")
    if not isinstance(ok, bool):
        raise ProtocolError("Invalid 'ok' in response")

    req_id = msg.get("req_id")
    if req_id is not None and not isinstance(req_id, str):
        raise ProtocolError("Invalid 'req_id' in response")

    result = msg.get("result")
    error = msg.get("error")
    if error is not None and not isinstance(error, dict):
        raise ProtocolError("Invalid 'error' in response")

    return ok, req_id, result, error


def pack_message_for_tests(payload: dict[str, Any]) -> dict[str, Any]:
    return decode_message_bytes(encode_message(payload)[_LENGTH_STRUCT.size :])
