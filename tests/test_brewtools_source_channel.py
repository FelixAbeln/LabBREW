from __future__ import annotations

import pytest

from Services.parameterDB.sourceDefs.brewtools.service import BrewtoolsSource
from Services.parameterDB.sourceDefs.brewtools.service import BrewtoolsCanSourceError
from Services.parameterDB.sourceDefs.brewtools.transports.base import RawCanFrame


class _FakeClient:
    def __init__(self):
        self.values = {}

    def set_value(self, _name, _value):
        return None

    def get_value(self, name, default=None):
        return self.values.get(name, default)


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


def test_brewtools_connect_transport_reuses_channel_validation_for_kvaser(monkeypatch) -> None:
    from Services.parameterDB.sourceDefs.brewtools import service as brewtools_service

    class _FakeKvaserTransport:
        def __init__(self, **_kwargs):
            return None

        def close(self):
            return None

    monkeypatch.setattr(brewtools_service, "KvaserTransport", _FakeKvaserTransport)

    source = BrewtoolsSource(
        "brewcan",
        _FakeClient(),
        config={"transport": "kvaser", "channel": "abc"},
    )

    with pytest.raises(BrewtoolsCanSourceError, match="expected an integer"):
        source._connect_transport()


def test_apply_outputs_uses_configured_agitator_nodes_without_discovery() -> None:
    client = _FakeClient()
    source = BrewtoolsSource(
        "brewcan",
        client,
        config={
            "transport": "pcan_gateway_udp",
            "parameter_prefix": "brewcan",
            "channel": 0,
            "agitator_nodes": [0],
        },
    )

    client.values["brewcan.agitator.0.set_pwm"] = 40

    class _FakeTransport:
        def __init__(self):
            self.sent = []

        def send_frame(self, frame):
            self.sent.append(frame)

    transport = _FakeTransport()
    source._apply_outputs(transport)

    assert len(transport.sent) == 1
    assert transport.sent[0].arbitration_id == 0x840301B
    assert transport.sent[0].data == b"\x00\x28"