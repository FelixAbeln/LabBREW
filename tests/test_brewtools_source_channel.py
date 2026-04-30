from __future__ import annotations

import pytest

from Services.parameterDB.sourceDefs.brewtools.service import BrewtoolsSource
from Services.parameterDB.sourceDefs.brewtools.service import BrewtoolsCanSourceError
from Services.parameterDB.sourceDefs.brewtools.transports.base import RawCanFrame


class _FakeClient:
    def set_value(self, _name, _value):
        return None


def test_brewtools_build_raw_frame_uses_configured_channel() -> None:
    source = BrewtoolsSource(
        "brewcan",
        _FakeClient(),
        config={"transport": "pcan_gateway_udp", "channel": 1},
    )

    frame = source._build_raw_frame(0x123, b"\x01\x02")

    assert frame.channel == 1
    assert frame.arbitration_id == 0x123
    assert frame.data == b"\x01\x02"


def test_receive_frames_filters_to_configured_channel() -> None:
    """Frames whose channel byte doesn't match config.channel must be dropped."""
    source = BrewtoolsSource(
        "brewcan",
        _FakeClient(),
        config={"transport": "pcan_gateway_udp", "channel": 1, "parameter_prefix": "brewcan"},
    )

    # Build one raw frame on channel 0 (wrong) and one on channel 1 (correct).
    # Use a minimal Brewtools CAN ID that won't raise in CanFrame.from_can.
    from Services.parameterDB.sourceDefs.brewtools.brewtools_can import BrewtoolsCanId, Priority
    from Services.parameterDB.sourceDefs.brewtools.brewtools_can.enums import MsgType, NodeType

    can_id = BrewtoolsCanId(
        priority=int(Priority.MEDIUM),
        sender_node_type=int(NodeType.NODE_TYPE_PLC),
        receiver_node_type=int(NodeType.NODE_TYPE_PLC),
        secondary_node_id=1,
        msg_type=int(MsgType.MSG_TYPE_PWM),
    )
    arb_id = can_id.to_arbitration_id()

    wrong_channel_frame = RawCanFrame(arbitration_id=arb_id, data=b"\x00", channel=0)
    right_channel_frame = RawCanFrame(arbitration_id=arb_id, data=b"\x00", channel=1)

    class _FakeTransport:
        def recv_frames(self, timeout=None):
            return [wrong_channel_frame, right_channel_frame]

    results = source._receive_frames(_FakeTransport(), timeout_s=0.0)

    # Only the frame from channel 1 should pass through.
    assert len(results) == 1


@pytest.mark.parametrize("bad_channel", [-1, 256, 999])
def test_brewtools_build_raw_frame_rejects_out_of_range_channel(bad_channel: int) -> None:
    source = BrewtoolsSource(
        "brewcan",
        _FakeClient(),
        config={"transport": "pcan_gateway_udp", "channel": bad_channel},
    )

    with pytest.raises(BrewtoolsCanSourceError, match="range 0..255"):
        source._build_raw_frame(0x123, b"\x01")


def test_brewtools_build_raw_frame_rejects_non_integer_channel() -> None:
    source = BrewtoolsSource(
        "brewcan",
        _FakeClient(),
        config={"transport": "pcan_gateway_udp", "channel": "abc"},
    )

    with pytest.raises(BrewtoolsCanSourceError, match="expected an integer"):
        source._build_raw_frame(0x123, b"\x01")