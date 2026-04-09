from __future__ import annotations

from io import BytesIO

import msgpack
import pytest

from Services.parameterDB.parameterdb_core.errors import ProtocolError
from Services.parameterDB.parameterdb_core.protocol import (
    _LENGTH_STRUCT,
    PROTOCOL_VERSION,
    _read_exact,
    decode_message_bytes,
    encode_message,
    make_error_response,
    make_request,
    make_response,
    pack_message_for_tests,
    read_message,
    validate_request_envelope,
    validate_response_envelope,
)


class ChunkedStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def read(self, _size: int) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def test_decode_message_bytes_rejects_invalid_payload_and_non_dict() -> None:
    with pytest.raises(ProtocolError, match="Invalid message payload"):
        decode_message_bytes(b"not-msgpack")

    with pytest.raises(ProtocolError, match="Message must be a map/object"):
        decode_message_bytes(msgpack.packb([1, 2, 3], use_bin_type=True))


def test_read_exact_handles_partial_and_empty_streams() -> None:
    assert _read_exact(BytesIO(b""), 4) is None

    stream = ChunkedStream([b"ab", b"cd"])
    assert _read_exact(stream, 4) == b"abcd"

    incomplete = ChunkedStream([b"ab", b""])
    with pytest.raises(ProtocolError, match="Incomplete framed message"):
        _read_exact(incomplete, 4)


def test_read_message_handles_invalid_lengths_and_roundtrip() -> None:
    assert read_message(BytesIO(b"")) is None

    zero_length = BytesIO(_LENGTH_STRUCT.pack(0))
    with pytest.raises(ProtocolError, match="Invalid frame length"):
        read_message(zero_length)

    missing_body = BytesIO(_LENGTH_STRUCT.pack(5))
    with pytest.raises(ProtocolError, match="Incomplete message body"):
        read_message(missing_body)

    payload = {"v": PROTOCOL_VERSION, "cmd": "ping", "payload": {"x": 1}}
    assert read_message(BytesIO(encode_message(payload))) == payload


def test_make_request_response_and_error_response_helpers() -> None:
    request = make_request("ping", {"x": 1}, req_id="r1")
    assert request == {"v": PROTOCOL_VERSION, "req_id": "r1", "cmd": "ping", "payload": {"x": 1}}

    generated = make_request("ping")
    assert generated["v"] == PROTOCOL_VERSION
    assert generated["cmd"] == "ping"
    assert generated["payload"] == {}
    assert isinstance(generated["req_id"], str)
    assert generated["req_id"]

    with pytest.raises(ProtocolError, match="non-empty string"):
        make_request("   ")

    assert make_response(req_id="r1", result={"ok": True}) == {
        "v": PROTOCOL_VERSION,
        "req_id": "r1",
        "ok": True,
        "result": {"ok": True},
        "error": None,
    }
    assert make_error_response(req_id="r1", error_type="Boom", message="bad") == {
        "v": PROTOCOL_VERSION,
        "req_id": "r1",
        "ok": False,
        "result": None,
        "error": {"type": "Boom", "message": "bad"},
    }


def test_validate_request_envelope_accepts_and_rejects_expected_shapes() -> None:
    assert validate_request_envelope({"v": 1, "cmd": "ping", "req_id": "r1", "payload": {"x": 1}}) == (
        "ping",
        "r1",
        {"x": 1},
    )

    with pytest.raises(ProtocolError, match="Request must be a dict"):
        validate_request_envelope([])  # type: ignore[arg-type]
    with pytest.raises(ProtocolError, match="Unsupported protocol version"):
        validate_request_envelope({"v": 2, "cmd": "ping", "payload": {}})
    with pytest.raises(ProtocolError, match="Missing or invalid 'cmd'"):
        validate_request_envelope({"v": 1, "cmd": " ", "payload": {}})
    with pytest.raises(ProtocolError, match="Invalid 'req_id'"):
        validate_request_envelope({"v": 1, "cmd": "ping", "req_id": 123, "payload": {}})
    with pytest.raises(ProtocolError, match="Invalid 'payload', expected dict"):
        validate_request_envelope({"v": 1, "cmd": "ping", "payload": []})


def test_validate_response_envelope_accepts_and_rejects_expected_shapes() -> None:
    assert validate_response_envelope({"v": 1, "ok": True, "req_id": "r1", "result": 7, "error": None}) == (
        True,
        "r1",
        7,
        None,
    )

    with pytest.raises(ProtocolError, match="Response must be a dict"):
        validate_response_envelope([])  # type: ignore[arg-type]
    with pytest.raises(ProtocolError, match="Unsupported protocol version"):
        validate_response_envelope({"v": 2, "ok": True})
    with pytest.raises(ProtocolError, match="Invalid 'ok' in response"):
        validate_response_envelope({"v": 1, "ok": "yes"})
    with pytest.raises(ProtocolError, match="Invalid 'req_id' in response"):
        validate_response_envelope({"v": 1, "ok": True, "req_id": 1})
    with pytest.raises(ProtocolError, match="Invalid 'error' in response"):
        validate_response_envelope({"v": 1, "ok": False, "error": "bad"})


def test_pack_message_for_tests_roundtrips_payload() -> None:
    payload = {"v": 1, "payload": {"nested": [1, 2, 3]}}
    assert pack_message_for_tests(payload) == payload
