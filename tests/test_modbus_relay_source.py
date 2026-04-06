from __future__ import annotations

import pytest

from Services.parameterDB.sourceDefs.modbus_relay.service import (
    ModbusRelaySource,
    RelayBoard,
    RelayError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeClient:
    """Minimal SupportsSignalRequests-compatible stub."""

    def __init__(self, initial: dict | None = None) -> None:
        self._store: dict = dict(initial or {})
        self.written: list[tuple[str, object]] = []

    def get_value(self, name: str, default=None):
        return self._store.get(name, default)

    def set_value(self, name: str, value) -> None:
        self._store[name] = value
        self.written.append((name, value))

    def ensure_parameter(self, name, param_type, *, value=None, metadata=None) -> None:
        if name not in self._store:
            self._store[name] = value

    def update_metadata(self, name, **kwargs) -> None:
        pass

    def snapshot(self, names=None):
        if names is None:
            return dict(self._store)
        return {k: self._store[k] for k in names if k in self._store}


class _FakeBoard:
    """Fake relay board that tracks hardware state independently."""

    def __init__(self, channel_count: int = 2, initial: dict[int, bool] | None = None) -> None:
        self._states: dict[int, bool] = {ch: False for ch in range(1, channel_count + 1)}
        if initial:
            self._states.update(initial)
        self.set_calls: list[tuple[int, bool]] = []

    def all_states(self) -> dict[int, bool]:
        return dict(self._states)

    def set_channel(self, channel: int, value: bool) -> None:
        self.set_calls.append((channel, value))
        self._states[channel] = value

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass


def _make_source(client: _FakeClient, channel_count: int = 2) -> ModbusRelaySource:
    src = ModbusRelaySource(
        "relay",
        client,
        config={
            "host": "127.0.0.1",
            "parameter_prefix": "relay",
            "channel_count": channel_count,
        },
    )
    return src


# ---------------------------------------------------------------------------
# Basic sync behaviour
# ---------------------------------------------------------------------------

def test_sync_turns_on_relay_when_desired_differs():
    """Board OFF → paramDB desires ON → board should be switched ON."""
    client = _FakeClient({"relay.ch1": True, "relay.ch2": False})
    src = _make_source(client)
    board = _FakeBoard(initial={1: False, 2: False})

    src._sync_once(board)

    assert board._states[1] is True   # board was turned on
    assert board._states[2] is False  # ch2 stays off


def test_sync_turns_off_relay_when_desired_differs():
    """Board ON → paramDB desires OFF → board should be switched OFF."""
    client = _FakeClient({"relay.ch1": False})
    src = _make_source(client, channel_count=1)
    board = _FakeBoard(channel_count=1, initial={1: True})

    src._sync_once(board)

    assert board._states[1] is False


def test_sync_publishes_actual_state_back_to_paramdb():
    """After syncing, actual board state is written back to parameterDB."""
    client = _FakeClient({"relay.ch1": True, "relay.ch2": False})
    src = _make_source(client)
    board = _FakeBoard(initial={1: False, 2: False})

    src._sync_once(board)

    assert client.get_value("relay.ch1") is True   # board is now on, published
    assert client.get_value("relay.ch2") is False  # board is still off, published


# ---------------------------------------------------------------------------
# Race-condition fix: concurrent write must not be overwritten
# ---------------------------------------------------------------------------

def test_sync_does_not_overwrite_concurrent_write():
    """
    Race: a paramDB write arrives mid-cycle (between reading desired states
    and publishing actual board states).  The sync must NOT overwrite the
    concurrent write with the stale board state, or the write is permanently
    lost and the relay stays in the wrong state indefinitely.
    """
    # Initial state: ch1 is OFF in both paramDB and on the board.
    client = _FakeClient({"relay.ch1": False})
    src = _make_source(client, channel_count=1)
    board = _FakeBoard(channel_count=1, initial={1: False})

    # Patch _desired_states so the FIRST call returns the pre-write snapshot
    # (ch1 = False) and the SECOND call (post_desired re-read) returns the
    # value that the user wrote mid-cycle (ch1 = True).
    call_count = 0
    original_desired = src._desired_states

    def patched_desired():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {1: False}   # state before the concurrent write
        # Simulate user writing True to paramDB during the sync cycle
        client._store["relay.ch1"] = True
        return {1: True}        # state after the concurrent write

    src._desired_states = patched_desired

    src._sync_once(board)

    # The board is still off (no set_channel was called, because desired==actual
    # at the time we read them both as False)
    assert not board.set_calls, "Board should not have been toggled"

    # CRITICAL: paramDB must still hold True (the user's concurrent write),
    # NOT False (what the board just confirmed as its state).
    assert client.get_value("relay.ch1") is True, (
        "Concurrent write was overwritten — the relay will be stuck in wrong state"
    )


def test_sync_does_not_overwrite_concurrent_turn_off():
    """Symmetric: concurrent write from ON→OFF must also survive."""
    client = _FakeClient({"relay.ch1": True})
    src = _make_source(client, channel_count=1)
    board = _FakeBoard(channel_count=1, initial={1: True})

    call_count = 0

    def patched_desired():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {1: True}
        client._store["relay.ch1"] = False
        return {1: False}

    src._desired_states = patched_desired

    src._sync_once(board)

    assert client.get_value("relay.ch1") is False, (
        "Concurrent turn-off write was overwritten"
    )


def test_sync_publishes_board_failure_when_no_concurrent_write():
    """
    If the board fails to switch (actual != desired), the failure IS published
    so long as no concurrent write happened — this gives correct feedback.
    """
    client = _FakeClient({"relay.ch1": True})
    src = _make_source(client, channel_count=1)

    # Board that ignores writes (simulates a stuck relay)
    class _StuckBoard:
        def all_states(self):
            return {1: False}  # never changes

        def set_channel(self, channel, value):
            pass  # silently fails

    src._sync_once(_StuckBoard())

    # Board is stuck off; paramDB should reflect the actual hardware state so
    # the user can see it didn't apply.
    assert client.get_value("relay.ch1") is False
